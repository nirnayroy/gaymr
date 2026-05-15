// Package awsmanaged implements the providers.Provider interface against
// AWS-owned EC2 GPU instances. Phase 2A: launches g4dn.xlarge on-demand,
// reuses an idempotent security group, then runs the Phase-1 provision.sh
// over SSH against the new instance.
package awsmanaged

import (
	"context"
	"errors"
	"fmt"
	"os/exec"
	"path/filepath"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/ec2"
	ec2types "github.com/aws/aws-sdk-go-v2/service/ec2/types"
	"github.com/aws/aws-sdk-go-v2/service/ssm"

	"github.com/gaymr/gaymr/internal/providers"
)

const providerName = "aws-managed"

type Config struct {
	Region          string // AWS region for GPU nodes
	AMIParam        string // SSM parameter for DLAMI
	KeyPair         string // EC2 keypair name
	SecurityGroupID string // optional pre-created SG; otherwise we create one
	ProvisionScript string // absolute path to provision-remote.sh
	SSHKeyPath      string // absolute path to private key matching KeyPair
}

type Provider struct {
	cfg Config
	ec2 *ec2.Client
	ssm *ssm.Client
}

func New(ctx context.Context, cfg Config) (*Provider, error) {
	if cfg.Region == "" || cfg.KeyPair == "" || cfg.AMIParam == "" {
		return nil, errors.New("aws-managed: region, key pair, and AMI param required")
	}
	awsCfg, err := awsconfig.LoadDefaultConfig(ctx, awsconfig.WithRegion(cfg.Region))
	if err != nil {
		return nil, fmt.Errorf("load aws config: %w", err)
	}
	return &Provider{
		cfg: cfg,
		ec2: ec2.NewFromConfig(awsCfg),
		ssm: ssm.NewFromConfig(awsCfg),
	}, nil
}

func (p *Provider) Name() string { return providerName }

func (p *Provider) EstimatedCostPerSecond(sku string) (float64, error) {
	switch sku {
	case "g4dn.xlarge":
		return 0.526 / 3600.0, nil
	}
	return 0, providers.ErrUnsupportedSKU
}

func (p *Provider) GetStatus(ctx context.Context, nodeID string) (*providers.NodeStatus, error) {
	out, err := p.ec2.DescribeInstances(ctx, &ec2.DescribeInstancesInput{
		InstanceIds: []string{nodeID},
	})
	if err != nil {
		return nil, err
	}
	if len(out.Reservations) == 0 || len(out.Reservations[0].Instances) == 0 {
		return &providers.NodeStatus{NodeID: nodeID, State: "terminated"}, nil
	}
	inst := out.Reservations[0].Instances[0]
	return &providers.NodeStatus{
		NodeID: nodeID,
		State:  string(inst.State.Name),
	}, nil
}

func (p *Provider) Provision(ctx context.Context, req providers.SessionRequest) (*providers.Node, error) {
	if req.SKU != "g4dn.xlarge" {
		return nil, providers.ErrUnsupportedSKU
	}
	amiID, err := p.resolveAMI(ctx)
	if err != nil {
		return nil, err
	}
	sgID, err := p.ensureSecurityGroup(ctx)
	if err != nil {
		return nil, err
	}
	runOut, err := p.ec2.RunInstances(ctx, &ec2.RunInstancesInput{
		ImageId:          aws.String(amiID),
		InstanceType:     ec2types.InstanceType(req.SKU),
		KeyName:          aws.String(p.cfg.KeyPair),
		SecurityGroupIds: []string{sgID},
		MinCount:         aws.Int32(1),
		MaxCount:         aws.Int32(1),
		BlockDeviceMappings: []ec2types.BlockDeviceMapping{{
			DeviceName: aws.String("/dev/sda1"),
			Ebs: &ec2types.EbsBlockDevice{
				VolumeSize:          aws.Int32(100),
				VolumeType:          ec2types.VolumeTypeGp3,
				DeleteOnTermination: aws.Bool(true),
			},
		}},
		InstanceInitiatedShutdownBehavior: ec2types.ShutdownBehaviorTerminate,
		TagSpecifications: []ec2types.TagSpecification{{
			ResourceType: ec2types.ResourceTypeInstance,
			Tags: []ec2types.Tag{
				{Key: aws.String("Name"), Value: aws.String("gaymr-" + req.SessionID)},
				{Key: aws.String("project"), Value: aws.String("gaymr")},
				{Key: aws.String("session_id"), Value: aws.String(req.SessionID)},
				{Key: aws.String("user_id"), Value: aws.String(req.UserID)},
			},
		}},
	})
	if err != nil {
		return nil, fmt.Errorf("run instances: %w", err)
	}
	if len(runOut.Instances) == 0 {
		return nil, errors.New("run instances returned no instance")
	}
	instanceID := *runOut.Instances[0].InstanceId

	publicIP, err := p.waitForRunning(ctx, instanceID, 5*time.Minute)
	if err != nil {
		_ = p.terminateBestEffort(ctx, instanceID)
		return nil, err
	}

	if err := p.runProvision(ctx, publicIP); err != nil {
		_ = p.terminateBestEffort(ctx, instanceID)
		return nil, fmt.Errorf("remote provision: %w", err)
	}

	return &providers.Node{
		NodeID:    instanceID,
		PublicIP:  publicIP,
		Region:    p.cfg.Region,
		SKU:       req.SKU,
		StartedAt: time.Now().UTC(),
	}, nil
}

func (p *Provider) Terminate(ctx context.Context, nodeID string) error {
	_, err := p.ec2.TerminateInstances(ctx, &ec2.TerminateInstancesInput{
		InstanceIds: []string{nodeID},
	})
	return err
}

func (p *Provider) terminateBestEffort(ctx context.Context, id string) error {
	tctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	_ = ctx
	return p.Terminate(tctx, id)
}

func (p *Provider) resolveAMI(ctx context.Context) (string, error) {
	out, err := p.ssm.GetParameter(ctx, &ssm.GetParameterInput{Name: aws.String(p.cfg.AMIParam)})
	if err != nil {
		return "", fmt.Errorf("ssm get parameter: %w", err)
	}
	return *out.Parameter.Value, nil
}

func (p *Provider) ensureSecurityGroup(ctx context.Context) (string, error) {
	if p.cfg.SecurityGroupID != "" {
		return p.cfg.SecurityGroupID, nil
	}
	const name = "gaymr-sunshine-sg"
	out, err := p.ec2.DescribeSecurityGroups(ctx, &ec2.DescribeSecurityGroupsInput{
		Filters: []ec2types.Filter{{Name: aws.String("group-name"), Values: []string{name}}},
	})
	if err == nil && len(out.SecurityGroups) > 0 {
		return *out.SecurityGroups[0].GroupId, nil
	}
	return "", fmt.Errorf("security group %q not found; run infra/sunshine-node/launch.sh once or set AWS_GPU_SG_ID", name)
}

func (p *Provider) waitForRunning(ctx context.Context, instanceID string, timeout time.Duration) (string, error) {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		out, err := p.ec2.DescribeInstances(ctx, &ec2.DescribeInstancesInput{
			InstanceIds: []string{instanceID},
		})
		if err != nil {
			return "", err
		}
		if len(out.Reservations) > 0 && len(out.Reservations[0].Instances) > 0 {
			inst := out.Reservations[0].Instances[0]
			if inst.State.Name == ec2types.InstanceStateNameRunning && inst.PublicIpAddress != nil {
				return *inst.PublicIpAddress, nil
			}
		}
		select {
		case <-ctx.Done():
			return "", ctx.Err()
		case <-time.After(5 * time.Second):
		}
	}
	return "", fmt.Errorf("instance %s did not reach running state within %s", instanceID, timeout)
}

func (p *Provider) runProvision(ctx context.Context, publicIP string) error {
	if p.cfg.ProvisionScript == "" {
		return errors.New("ProvisionScript path not configured")
	}
	script, err := filepath.Abs(p.cfg.ProvisionScript)
	if err != nil {
		return err
	}
	cctx, cancel := context.WithTimeout(ctx, 10*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(cctx, "bash", script, publicIP)
	cmd.Dir = filepath.Dir(script)
	if p.cfg.SSHKeyPath != "" {
		cmd.Env = append(cmd.Environ(), "KEY="+p.cfg.SSHKeyPath)
	}
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("provision script failed: %w\n%s", err, truncate(string(out), 4000))
	}
	return nil
}

func truncate(s string, max int) string {
	if len(s) <= max {
		return s
	}
	return "...[truncated]\n" + s[len(s)-max:]
}
